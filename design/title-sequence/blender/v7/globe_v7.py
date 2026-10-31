"""Title v7 "The Record Stands": the Doppelmayr globe scan as numbers (no bpy, no I/O beyond reading the gated scan).

The scan (run-scan-ledger.json id "globe", gate pass) is read straight from its glTF buffers: the sphere and the
meridian ring are kept, the stand, horizon ring, legs and under-table mat are not (v7-beats.json world.globe).
Everything here works in the scan's own mesh coordinates ("native": z up, the units of scene.bin) or in the globe
frame ("geo": z the polar axis to the north, x through modern longitude 0, y through 90E), joined by the
registration rotation `R_geo_to_native`.

- `load()`: positions, uvs and triangles per kept part.
- `fit_sphere()`: centre and radius of the ball (least squares on the sphere part's vertices).
- `texel_density()`: source px per mm of surface on the sphere at a given diameter (UV area over mesh area,
  per triangle, the median over the lit hemisphere or all of it).
- `Caster`: ray from the centre to the surface: the triangle it hits and its uv (a KD-tree on triangle directions,
  then an exact ray-triangle test), so lat/lon -> uv -> texture pixel.
- `unwrap()`: an equirectangular image of the scan in any frame (registration evidence; never shown on screen).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

GLOBE_DIR = Path("D:/document-media/title-sequence/run/assets/globe")
GLTF = GLOBE_DIR / "scene.gltf"
KEEP = ("sphere", "ring")
SPHERE_TEX = GLOBE_DIR / "textures/sphere_baseColor.jpeg"
SPHERE_RM = GLOBE_DIR / "textures/sphere_metallicRoughness.png"
RING_TEX = GLOBE_DIR / "textures/ring_baseColor.jpeg"
RING_RM = GLOBE_DIR / "textures/ring_metallicRoughness.png"
TEX_PX = 8192

_COMP = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def _accessor(g, buf, i):
    a = g["accessors"][i]
    bv = g["bufferViews"][a["bufferView"]]
    n = _NCOMP[a["type"]]
    dt = _COMP[a["componentType"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride")
    item = np.dtype(dt).itemsize * n
    if stride and stride != item:
        raw = np.frombuffer(buf, np.uint8, a["count"] * stride, off).reshape(a["count"], stride)[:, :item]
        out = raw.copy().view(dt).reshape(a["count"], n)
    else:
        out = np.frombuffer(buf, dt, a["count"] * n, off).reshape(a["count"], n)
    return out if n > 1 else out[:, 0]


def load(gltf: Path = GLTF, keep=KEEP) -> dict:
    """{part: {"P": (n,3) float64 native, "UV": (n,2) glTF uv (v down), "T": (m,3) int}} for the kept materials."""
    g = json.loads(gltf.read_text(encoding="utf-8"))
    buf = (gltf.parent / g["buffers"][0]["uri"]).read_bytes()
    out: dict = {}
    for m in g["meshes"]:
        for p in m["primitives"]:
            name = g["materials"][p["material"]]["name"]
            if name not in keep:
                continue
            P = _accessor(g, buf, p["attributes"]["POSITION"]).astype(np.float64)
            UV = _accessor(g, buf, p["attributes"]["TEXCOORD_0"]).astype(np.float64)
            T = _accessor(g, buf, p["indices"]).astype(np.int64).reshape(-1, 3)
            if name in out:                      # several primitives of one material: concatenate
                k = len(out[name]["P"])
                out[name] = {"P": np.vstack([out[name]["P"], P]), "UV": np.vstack([out[name]["UV"], UV]),
                             "T": np.vstack([out[name]["T"], T + k])}
            else:
                out[name] = {"P": P, "UV": UV, "T": T}
    missing = [k for k in keep if k not in out]
    if missing:
        raise ValueError(f"scan parts missing: {missing}")
    return out


def fit_sphere(P: np.ndarray) -> tuple[np.ndarray, float]:
    """Algebraic least-squares sphere: |p|^2 = 2 c.p + (r^2 - |c|^2)."""
    A = np.hstack([2 * P, np.ones((len(P), 1))])
    b = (P ** 2).sum(1)
    x, *_ = np.linalg.lstsq(A, b, rcond=None)
    c = x[:3]
    r = math.sqrt(x[3] + c @ c)
    return c, r


def tri_areas(P, T):
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)


def uv_areas(UV, T, px=TEX_PX):
    a, b, c = UV[T[:, 0]] * px, UV[T[:, 1]] * px, UV[T[:, 2]] * px
    return 0.5 * np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1]))


def texel_density(part: dict, radius_native: float, diameter_m: float, mask=None) -> dict:
    """Source px per mm of surface with the ball scaled to diameter_m: sqrt(uv px^2 / surface mm^2) per triangle."""
    k = diameter_m / (2 * radius_native) * 1000.0               # native units -> mm
    A = tri_areas(part["P"], part["T"]) * k * k
    U = uv_areas(part["UV"], part["T"])
    ok = (A > 0) & (U > 0)
    if mask is not None:
        ok &= mask
    d = np.sqrt(U[ok] / A[ok])
    w = A[ok]
    order = np.argsort(d)
    cw = np.cumsum(w[order]) / w.sum()
    return {"median_px_per_mm": float(d[order][np.searchsorted(cw, 0.5)]),
            "p10": float(d[order][np.searchsorted(cw, 0.1)]), "p90": float(d[order][np.searchsorted(cw, 0.9)]),
            "area_weighted": True, "triangles": int(ok.sum()),
            "uv_used_fraction": float(U[ok].sum() / TEX_PX ** 2)}


class Caster:
    """Rays from the ball's centre to its surface: which triangle and which uv (exact Moller-Trumbore on the k
    triangles whose directions are nearest)."""

    def __init__(self, part: dict, centre: np.ndarray, k: int = 12):
        from scipy.spatial import cKDTree
        self.P, self.UV, self.T, self.c = part["P"], part["UV"], part["T"], centre
        cen = self.P[self.T].mean(1) - centre
        self.dirs = cen / np.linalg.norm(cen, axis=1, keepdims=True)
        self.tree = cKDTree(self.dirs)
        self.k = k

    def cast(self, D: np.ndarray, batch: int = 200_000):
        """D (n,3) unit directions in native -> (uv (n,2), hit point (n,3), ok (n,))."""
        n = len(D)
        uv = np.full((n, 2), np.nan)
        hit = np.full((n, 3), np.nan)
        ok = np.zeros(n, bool)
        for s in range(0, n, batch):
            d = D[s:s + batch]
            _, idx = self.tree.query(d, k=self.k)
            best_t = np.full(len(d), np.inf)
            for j in range(self.k):
                tri = self.T[idx[:, j]]
                a, b, c = self.P[tri[:, 0]], self.P[tri[:, 1]], self.P[tri[:, 2]]
                e1, e2 = b - a, c - a
                pv = np.cross(d, e2)
                det = (e1 * pv).sum(1)
                good = np.abs(det) > 1e-12
                inv = np.where(good, 1.0 / np.where(good, det, 1.0), 0.0)
                tv = self.c - a
                u = (tv * pv).sum(1) * inv
                qv = np.cross(tv, e1)
                v = (d * qv).sum(1) * inv
                t = (e2 * qv).sum(1) * inv
                inside = good & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > 0) & (t < best_t)
                if inside.any():
                    w0 = 1 - u - v
                    uvt = (self.UV[tri[:, 0]] * w0[:, None] + self.UV[tri[:, 1]] * u[:, None] +
                           self.UV[tri[:, 2]] * v[:, None])
                    uv[s:s + batch][inside] = uvt[inside]
                    hit[s:s + batch][inside] = (self.c + d * t[:, None])[inside]
                    best_t = np.where(inside, t, best_t)
            ok[s:s + batch] = np.isfinite(best_t)
        return uv, hit, ok


def geo_dir(lat_deg, lon_deg):
    la, lo = np.radians(lat_deg), np.radians(lon_deg)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], -1)


def dir_geo(D):
    D = np.asarray(D, float)
    return np.degrees(np.arcsin(np.clip(D[..., 2], -1, 1))), np.degrees(np.arctan2(D[..., 1], D[..., 0]))


def frame_from_pole(pole: np.ndarray, zero: np.ndarray) -> np.ndarray:
    """R (3x3) taking geo vectors to native: columns are geo x (lon 0 on the equator), geo y, geo z (the pole)."""
    z = pole / np.linalg.norm(pole)
    x = zero - z * (zero @ z)
    x /= np.linalg.norm(x)
    return np.stack([x, np.cross(z, x), z], 1)


def rot_about(axis, deg):
    a = np.asarray(axis, float) / np.linalg.norm(axis)
    t = math.radians(deg)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * K @ K


def sample(img: np.ndarray, uv: np.ndarray) -> np.ndarray:
    """Nearest texel of a glTF uv (v from the top of the image)."""
    h, w = img.shape[:2]
    out = np.zeros((len(uv),) + img.shape[2:], img.dtype)
    ok = np.isfinite(uv).all(1)
    x = np.clip((uv[ok, 0] * w).astype(int), 0, w - 1)
    y = np.clip((uv[ok, 1] * h).astype(int), 0, h - 1)
    out[ok] = img[y, x]
    return out


def unwrap(caster: Caster, img: np.ndarray, R_geo_to_native: np.ndarray, width: int = 2048,
           lat=(-90.0, 90.0), lon=(-180.0, 180.0)) -> np.ndarray:
    """Equirectangular image (rows north to south) of the scan in the geo frame R names."""
    height = int(round(width * (lat[1] - lat[0]) / (lon[1] - lon[0])))
    la = np.linspace(lat[1], lat[0], height)
    lo = np.linspace(lon[0], lon[1], width)
    LO, LA = np.meshgrid(lo, la)
    D = geo_dir(LA.ravel(), LO.ravel()) @ R_geo_to_native.T
    uv, _, ok = caster.cast(D)
    px = sample(img, uv)
    px[~ok] = 0
    return px.reshape(height, width, -1)
