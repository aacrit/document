"""The Run v4, ticket 4's check: a contact shadow along an overlapping sheet edge (numpy, PIL; the D: venv).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/shadow_band.py \
        --frames-dir <dir> --frame 300 --edge leaf:-v [--camera camera-prefix.json]

The named edge of the upper sheet (bench.SHEETS) is sampled every 5 mm, projected into the rendered frame through the
camera plan, and at each visible sample the lower surface's luminance is read just outside the edge (2 to 6 px at
1080p, scaled to the frame's width) and further out (10 to 16 px). A sample shows a contact shadow when the near band is
at least 2 levels (8-bit) darker than the far band. Reports the share of visible samples with a shadow (the ticket
asks at least 80%) and the median darkening.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bench as B  # noqa: E402
import camera_run as CR  # noqa: E402

SIM = Path("D:/document-media/title-sequence/run/sim/v4")
RELIEF = Path("D:/document-media/title-sequence/run/relief")


def edge_points(sheet, edge, step=0.005):
    s = B.SHEETS[sheet]
    W, H = s["size"]
    p = math.radians(s["psi"])
    pts, outward = [], None
    if edge in ("-v", "+v"):
        v = -H / 2 if edge == "-v" else H / 2
        us = np.arange(-W / 2, W / 2, step)
        loc = [(u, v) for u in us]
        outward = (0.0, -1.0 if edge == "-v" else 1.0)
    else:
        u = -W / 2 if edge == "-u" else W / 2
        vs = np.arange(-H / 2, H / 2, step)
        loc = [(u, v) for v in vs]
        outward = (-1.0 if edge == "-u" else 1.0, 0.0)
    w = np.load(RELIEF / "world.npz")
    top = w["top"]
    for u, v in loc:
        x = s["centre"][0] + u * math.cos(p) - v * math.sin(p)
        y = s["centre"][1] + u * math.sin(p) + v * math.cos(p)
        i = int(np.clip((x - float(w["x0"])) / float(w["texel"]), 0, top.shape[1] - 1))
        j = int(np.clip((y - float(w["y0"])) / float(w["texel"]), 0, top.shape[0] - 1))
        pts.append((x, y, float(top[j, i])))
    ox = outward[0] * math.cos(p) - outward[1] * math.sin(p)
    oy = outward[0] * math.sin(p) + outward[1] * math.cos(p)
    return pts, (ox, oy)


def measure(img, rows, frame, sheet, edge):
    lum = np.asarray(img.convert("L"), np.float32)
    Hh, Ww = lum.shape
    k = Ww / 1920.0
    r = CR.at(rows, frame / 24)
    pts, (ox, oy) = edge_points(sheet, edge)
    res = []
    for x, y, z in pts:
        a = CR.project(r, (x, y, z))
        b = CR.project(r, (x + ox * 0.01, y + oy * 0.01, z))
        if a is None or b is None:
            continue
        a, b = a * k, b * k
        d = (b - a) / (np.linalg.norm(b - a) + 1e-9)
        if not (20 * k < a[0] < Ww - 20 * k and 20 * k < a[1] < Hh - 20 * k):
            continue

        def band(r0, r1):
            vals = []
            for t in np.linspace(r0, r1, 5):
                q = a + d * t * k
                vals.append(lum[int(np.clip(q[1], 0, Hh - 1)), int(np.clip(q[0], 0, Ww - 1))])
            return float(np.mean(vals))
        near, far = band(2, 6), band(10, 16)
        if far < 8:                                    # in the dark: no reading
            continue
        res.append(far - near)
    if not res:
        return {"sheet": sheet, "edge": edge, "frame": frame, "visible": 0}
    res = np.array(res)
    return {"sheet": sheet, "edge": edge, "frame": frame, "visible": int(len(res)),
            "share_with_shadow": round(float((res >= 2.0).mean()), 3), "median_darkening": round(float(np.median(res)), 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-dir", required=True)
    ap.add_argument("--frame", type=int, action="append", required=True)
    ap.add_argument("--edge", action="append", required=True, help="sheet:edge, e.g. leaf:-v")
    ap.add_argument("--camera", default=str(SIM / "camera-prefix.json"))
    a = ap.parse_args()
    rows = json.loads(Path(a.camera).read_text(encoding="utf-8"))["rows"]
    out = []
    for f in a.frame:
        img = Image.open(Path(a.frames_dir) / f"{f:04d}.png")
        for e in a.edge:
            sh, ed = e.split(":")
            out.append(measure(img, rows, f, sh, ed))
    print(json.dumps(out))


if __name__ == "__main__":
    main()
