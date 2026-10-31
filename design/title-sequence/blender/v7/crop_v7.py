"""Title v7: registration crops (evidence). An equirectangular crop of the scan in a frame, with a labelled grid.

    python crop_v7.py <name> <lat0> <lat1> <lon0> <lon1> <px_per_deg> [frame.json]
frame.json holds {"R": 3x3 geo->native}; without it the native frame is used. Writes register/crop-<name>.jpg.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "run"))
import globe_v7 as G  # noqa: E402
import machine_v6 as MV  # noqa: E402

OUT = Path("D:/document-media/title-sequence/v7/register")
Image.MAX_IMAGE_PIXELS = None


def main():
    MV.cap_memory(4.0)
    name, la0, la1, lo0, lo1, ppd = sys.argv[1], *map(float, sys.argv[2:7])
    R = np.array(json.loads(Path(sys.argv[7]).read_text())["R"]) if len(sys.argv) > 7 else np.eye(3)
    m = G.load()
    c, r = G.fit_sphere(m["sphere"]["P"])
    img = np.asarray(Image.open(G.SPHERE_TEX))
    cast = G.Caster(m["sphere"], c)
    U = G.unwrap(cast, img, R, width=int((lo1 - lo0) * ppd), lat=(la0, la1), lon=(lo0, lo1))
    im = Image.fromarray(U[..., :3])
    d = ImageDraw.Draw(im)
    step = 5 if (lo1 - lo0) <= 60 else 10
    for lo in np.arange(np.ceil(lo0 / step) * step, lo1 + 1e-6, step):
        x = (lo - lo0) * ppd
        d.line([(x, 0), (x, im.height)], fill=(255, 0, 0), width=1)
        d.text((x + 2, 2), f"{lo:.0f}", fill=(255, 0, 0))
    for la in np.arange(np.ceil(la0 / step) * step, la1 + 1e-6, step):
        y = (la1 - la) * ppd
        d.line([(0, y), (im.width, y)], fill=(0, 90, 255), width=1)
        d.text((2, y + 2), f"{la:.0f}", fill=(0, 90, 255))
    OUT.mkdir(parents=True, exist_ok=True)
    im.save(OUT / f"crop-{name}.jpg", quality=90)
    print(OUT / f"crop-{name}.jpg", im.size)


if __name__ == "__main__":
    main()
