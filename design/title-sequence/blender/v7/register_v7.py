"""Title v7: the globe's registration and texel density, measured on the gated scan (day 1; v7-beats.json world.globe).

    python design/title-sequence/blender/v7/register_v7.py native      # unwraps in the scan's own frame (evidence)
    python design/title-sequence/blender/v7/register_v7.py fit         # the fit from registration.json's picks

Writes to D:/document-media/title-sequence/v7/register/. Process capped at 4 GB (machine_v6.cap_memory).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "run"))
import globe_v7 as G  # noqa: E402
import machine_v6 as MV  # noqa: E402

OUT = Path("D:/document-media/title-sequence/v7/register")
Image.MAX_IMAGE_PIXELS = None


def native():
    OUT.mkdir(parents=True, exist_ok=True)
    m = G.load()
    c, r = G.fit_sphere(m["sphere"]["P"])
    res = np.linalg.norm(m["sphere"]["P"] - c, axis=1) - r
    R = m["ring"]["P"]
    rc = R.mean(0)
    w, V = np.linalg.eigh(np.cov((R - rc).T))
    rep = {"centre_native": c.tolist(), "radius_native": r, "sphere_resid_std": float(res.std()),
           "sphere_resid_max": float(np.abs(res).max()),
           "density_at_4m": G.texel_density(m["sphere"], r, 4.0),
           "ring_normal_native": V[:, 0].tolist(), "ring_eig": w.tolist(), "ring_centre_minus_ball": (rc - c).tolist()}
    print(json.dumps(rep, indent=1))
    img = np.asarray(Image.open(G.SPHERE_TEX).reduce(4))
    cast = G.Caster(m["sphere"], c)
    U = G.unwrap(cast, img, np.eye(3), width=2048)
    Image.fromarray(U).save(OUT / "unwrap-native.jpg", quality=88)
    # the ring-normal frame: z = ring normal, so the ring plane is the equator of this unwrap
    n = V[:, 0]
    zero = np.cross(n, [0, 0, 1.0])
    U2 = G.unwrap(cast, img, G.frame_from_pole(n, zero), width=2048)
    Image.fromarray(U2).save(OUT / "unwrap-ringnormal.jpg", quality=88)
    (OUT / "native.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")


def kabsch(picks):
    """R (geo->native) minimising the angle between R @ geo(lat, lon) and native(lat_n, lon_n) over the picks."""
    A = np.array([G.geo_dir(p["geo"][0], p["geo"][1]) for p in picks])
    B = np.array([G.geo_dir(p["native"][0], p["native"][1]) for p in picks])
    U, S, Vt = np.linalg.svd(A.T @ B)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1, 1, d]) @ U.T
    res = [float(np.degrees(np.arccos(np.clip((R @ a) @ b, -1, 1)))) for a, b in zip(A, B)]
    return R, res


def fit():
    reg = json.loads((HERE / "registration.json").read_text(encoding="utf-8"))
    R, res = kabsch(reg["picks"])
    rep = {"R": R.tolist(), "residual_deg": {p["name"]: round(x, 2) for p, x in zip(reg["picks"], res)},
           "rms_deg": float(np.sqrt(np.mean(np.square(res)))),
           "pole_native_latlon": [float(v) for v in G.dir_geo(R[:, 2])]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "frame.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))
    if "--unwrap" in sys.argv:
        from PIL import ImageDraw
        m = G.load()
        c, r = G.fit_sphere(m["sphere"]["P"])
        img = np.asarray(Image.open(G.SPHERE_TEX).reduce(4))
        U = G.unwrap(G.Caster(m["sphere"], c), img, R, width=2048)
        im = Image.fromarray(U[..., :3])
        d = ImageDraw.Draw(im)
        for lo in range(-180, 181, 30):
            x = (lo + 180) / 360 * im.width
            d.line([(x, 0), (x, im.height)], fill=(255, 0, 0))
        for la in range(-60, 61, 30):
            y = (90 - la) / 180 * im.height
            d.line([(0, y), (im.width, y)], fill=(0, 90, 255))
        for p in reg["picks"] + reg.get("checks", []):
            x, y = (p["geo"][1] + 180) / 360 * im.width, (90 - p["geo"][0]) / 180 * im.height
            d.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(0, 255, 0), width=2)
        im.save(OUT / "unwrap-geo.jpg", quality=88)


if __name__ == "__main__":
    MV.cap_memory(4.0)
    {"native": native, "fit": fit}[sys.argv[1]]()
