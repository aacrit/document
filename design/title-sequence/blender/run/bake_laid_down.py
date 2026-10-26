"""Laid Down: bake each sheet's relief and every frame's pose, the pile's heights included (numpy, scipy, PIL; D: venv).

    D:/document-media/tools/run-venv/Scripts/python.exe design/title-sequence/blender/run/bake_laid_down.py

A sheet is a rigid thin plate (spec section 4): its scan, its real thickness and its own relief at 2 mm a texel, made as
relief.py makes it, minus the curls and rolled edges the Run needed: (a) the scan's own fold relief (a 6-40 mm band-pass
of its luminance at relief.FOLD_AMP), (b) a low cockle along the sheet's grain, (c) every free edge 0.6 mm proud over
its last 15 mm, and Piri Reis's resting corner lifts (bench.SHEETS). The Atlas boards are rigid and flat with the hinge
dip on their faces. No pixel is made; the scans are only read.

The pile (spec section 4): a sheet rests on whatever is under it, its z the maximum of the heights its footprint covers
(the world top of the sheets already at rest, sampled on its texels; at a step the tilt is ignored and the contact
shadow kept). While it slides the same rule is applied every frame on its moving footprint.

Writes D:/document-media/title-sequence/laid-down/bake/plates.npz (per plate: top and bottom relative to the plate's
base, its mask), poses.json (per sheet and per record, per frame: centre, psi, z, lift, visible) and report.json (the
solved table, the rest heights, the gaps under each sheet's visible edges).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import laid_down as L  # noqa: E402

OUT = Path("D:/document-media/title-sequence/laid-down/bake")
TEX = Path("D:/document-media/title-sequence/tex")
TEXEL = 0.002
EDGE_PROUD = (0.0006, 0.015)                 # relief.EDGE_PROUD
FOLD_AMP = {"papyrus": 0.0003, "piri": 0.0004, "leaf": 0.0002, "ino": 0.0003, "chart": 0.0002}   # relief.FOLD_AMP
_PAP_W = 0.60                                # the papyrus itself on its mount (bench: 0.60 x 0.60 * 1481 / 8192)
LINEN_T = 0.0004                             # the linen mount under the 0.25 mm papyrus
ATLAS = (0.50, 0.50 * 3800 / 2760)           # bench.SHEETS atlas1/atlas2: each board 0.50 x 0.688
HINGE = {"gap": 0.0015, "depth": 0.0010, "half_w": 0.025}

# Each plate: the sheet it belongs to, its scan, its size (u along the image's width), its centre in the sheet's own
# frame, thickness, kind, and its relief. Cockle is local: (amp, wavelength, troughs' direction from +u in degrees).
# The cockle amplitudes are the bench's where they were not tuned to steer a marble, and held at 1.5 mm or less where
# they were: a rigid sheet rests on the highest point beneath it, so a deep cockle under it would lift it off the pile.
PLATES = [
    {"name": "papyrus", "sheet": "S1", "tex": "T-02a_keyed", "size": (0.62, 0.13), "at": (0.0, 0.0), "kind": "mount",
     "t": 0.00025 + LINEN_T, "fold_x": 0.35, "drape": 0.040},
    {"name": "atlas1", "sheet": "S2", "tex": "T-03_board1", "size": ATLAS, "at": (-(ATLAS[0] + HINGE["gap"]) / 2, 0.0),
     "kind": "board", "t": 0.0012, "hinge": "+u"},
    {"name": "atlas2", "sheet": "S2", "tex": "T-03_board2", "size": ATLAS, "at": ((ATLAS[0] + HINGE["gap"]) / 2, 0.0),
     "kind": "board", "t": 0.0012, "hinge": "-u"},
    {"name": "leaf", "sheet": "S3", "tex": "T-06_leaf", "size": (0.30, 0.42), "at": (0.0, 0.0), "kind": "paper",
     "t": 0.00015, "cockle": (0.0005, 0.15, 30.0)},
    {"name": "piri", "sheet": "S4", "tex": "T-04_keyed", "size": (0.65, 0.65 * 2619 / 1964), "at": (0.0, 0.0),
     "kind": "keyed", "t": 0.0003, "cockle": (0.0015, 0.15, 72.0), "corners": {"+u-v": 0.004, "-u-v": 0.004},
     "drape": 0.015},
    {"name": "ino", "sheet": "S5", "tex": "T-08_sheet", "size": (1.0, 1.0 * 4740 / 8192), "at": (0.0, 0.0),
     "kind": "paper", "t": 0.00008, "cockle": (0.0008, 0.15, 90.0)},
    {"name": "chart", "sheet": "S6", "tex": "T-20_chart", "size": (1.0, 1.0 * 5529 / 8192), "at": (0.0, 0.0),
     "kind": "paper", "t": 0.00012, "cockle": (0.0012, 0.15, 70.0)},
]
for _k, _r in L.RECORDS.items():
    PLATES.append({"name": f"record {_k}", "sheet": f"R {_k}", "tex": _r["tex"].rsplit(".", 1)[0],
                   "size": tuple(_r["size_m"]), "at": (0.0, 0.0), "kind": "paper", "t": 0.00012,
                   "cockle": (0.0002, 0.10, 20.0)})


def sheet_of(sid):
    if sid.startswith("R "):
        return L.RECORDS[sid[2:]]
    return L.BY_ID[sid]


def grid(pl):
    """Texel centres in the plate's own frame: (U, V), row 0 at +v (the scan's top)."""
    W, H = pl["size"]
    nu, nv = max(2, round(W / TEXEL)), max(2, round(H / TEXEL))
    u = -W / 2 + (np.arange(nu) + 0.5) * W / nu
    v = H / 2 - (np.arange(nv) + 0.5) * H / nv
    return np.meshgrid(u, v)


def scan(pl, shape):
    """The pinned scan's luminance and alpha on the plate's texels; for the mount, the papyrus on its central area."""
    from PIL import Image
    ext = ".png" if pl["kind"] in ("mount", "keyed") else ".jpg"
    im = Image.open(TEX / f"{pl['tex']}{ext}")
    if ext == ".jpg":
        im.draft("RGB", (shape[1] * 2, shape[0] * 2))
    rgba = np.asarray(im.convert("RGBA").resize((shape[1], shape[0]) if pl["kind"] != "mount" else
                                                mount_px(pl, shape), Image.BOX), np.float32) / 255.0
    if pl["kind"] == "mount":
        full = np.zeros(shape + (4,), np.float32)
        h, w = rgba.shape[:2]
        j0, i0 = (shape[0] - h) // 2, (shape[1] - w) // 2
        full[j0:j0 + h, i0:i0 + w] = rgba
        rgba = full
    lum = 0.2126 * rgba[..., 0] + 0.7152 * rgba[..., 1] + 0.0722 * rgba[..., 2]
    return lum, rgba[..., 3]


def mount_px(pl, shape):
    W, H = pl["size"]
    w = _PAP_W
    h = _PAP_W * 1481 / 8192
    return (int(round(shape[1] * w / W)), int(round(shape[0] * h / H)))


def mount_uv(pl):
    """The papyrus scan's place on its mount, as UV (u0, v0, u1, v1) of the mount's face."""
    W, H = pl["size"]
    w, h = _PAP_W, _PAP_W * 1481 / 8192
    return ((W - w) / 2 / W, (H - h) / 2 / H, (W + w) / 2 / W, (H + h) / 2 / H)


def own_relief(pl):
    """(top, bottom) relative to the plate's base, and its footprint mask, on its texels."""
    from scipy.ndimage import binary_fill_holes, distance_transform_edt, gaussian_filter
    U, V = grid(pl)
    W, H = pl["size"]
    lum, alpha = scan(pl, U.shape)
    mask = alpha > 0.5 if pl["kind"] == "keyed" else np.ones(U.shape, bool)
    if pl["kind"] == "keyed":
        mask = binary_fill_holes(mask)
    if pl["kind"] == "board":
        top = np.full(U.shape, pl["t"])
        dh = (W / 2 - U) if pl["hinge"] == "+u" else (U + W / 2)
        top -= HINGE["depth"] * (1 - np.clip(dh / HINGE["half_w"], 0, 1)) ** 2
        return top.astype(np.float32), np.zeros(U.shape, np.float32), mask
    rel = np.zeros(U.shape)
    amp = FOLD_AMP.get(pl["name"], 0.0)
    if amp:
        m = (alpha > 0.5) if pl["kind"] == "mount" else mask
        Lm = np.where(m, lum, np.nan)
        Lf = np.where(m, lum, np.nanmean(Lm))
        bp = gaussian_filter(Lf, 0.006 / TEXEL) - gaussian_filter(Lf, 0.040 / TEXEL)
        k = np.percentile(np.abs(bp[m]), 99) + 1e-9
        rel += np.where(m, np.clip(bp / k, -1, 1) * amp, 0.0)
    if pl.get("cockle"):
        a_, lam, deg = pl["cockle"]
        r = math.radians(deg)
        d = U * (-math.sin(r)) + V * math.cos(r)
        rel += a_ / 2 * (1 - np.cos(2 * math.pi * d / lam))
    if pl.get("fold_x"):
        u0 = -_PAP_W / 2 + pl["fold_x"] * _PAP_W
        rel += 0.0003 * np.exp(-0.5 * ((U - u0) / 0.004) ** 2)
    if pl["kind"] == "keyed":
        nearest = distance_transform_edt(mask) * TEXEL
    else:
        nearest = np.minimum.reduce([U + W / 2, W / 2 - U, V + H / 2, H / 2 - V])
    if pl["kind"] != "mount":                    # linen pasted on its board lies flat to its edge
        rel += EDGE_PROUD[0] * np.clip(1 - nearest / EDGE_PROUD[1], 0, 1) ** 2
    for c, lift in pl.get("corners", {}).items():
        du = (U + W / 2) if c[:2] == "-u" else (W / 2 - U)
        dv = (V + H / 2) if c[2:] == "-v" else (H / 2 - V)
        rel = np.maximum(rel, lift * np.clip(1 - np.hypot(du, dv) / 0.08, 0, 1) ** 2)
    rel -= rel[mask].min()
    return (rel + pl["t"]).astype(np.float32), rel.astype(np.float32), mask


def trailing(s):
    """The trailing corner (in the sheet's own frame) and its lift's reach: the near corner of the trailing edge."""
    side = s.get("enter_from")
    W, H = s["size_m"]
    corner = {"left": (-W / 2, -H / 2), "right": (W / 2, -H / 2), "bottom": (-W / 2, -H / 2)}[side]
    return corner, (0.12 if min(W, H) >= 0.3 else 0.06)


def lift_profile(pl, s):
    """The trailing corner's shape at 1.0 (m of lift per m of the key): paper bends up from its corner; the Atlas pair
    tilts as one rigid board, its trailing edge up."""
    U, V = grid(pl)
    U = U + pl["at"][0]
    V = V + pl["at"][1]
    if pl["kind"] == "board":
        W = 2 * ATLAS[0] + HINGE["gap"]
        sgn = 1.0 if s["enter_from"] == "right" else -1.0
        return np.clip(0.5 + sgn * U / W, 0, 1).astype(np.float32)
    (cu, cv), reach = trailing(s)
    d = np.hypot(U - cu, V - cv)
    return (np.clip(1 - d / reach, 0, 1) ** 2).astype(np.float32)


# ------------------------------------------------------------------------------------------------ the pile


class World:
    """The top of everything at rest, on a 2 mm grid over the whole table (pile coordinates)."""

    def __init__(self):
        W, H = L.TABLE["size"]
        self.x0, self.y0 = -L.P[0], -L.P[1]
        self.nx, self.ny = round(W / TEXEL), round(H / TEXEL)
        self.top = np.zeros((self.ny, self.nx), np.float32)

    def sample(self, X, Y):
        fi = (X - self.x0) / TEXEL - 0.5
        fj = (Y - self.y0) / TEXEL - 0.5
        i0 = np.clip(np.floor(fi).astype(int), 0, self.nx - 2)
        j0 = np.clip(np.floor(fj).astype(int), 0, self.ny - 2)
        ti, tj = np.clip(fi - i0, 0, 1), np.clip(fj - j0, 0, 1)
        a = self.top
        return (a[j0, i0] * (1 - ti) * (1 - tj) + a[j0, i0 + 1] * ti * (1 - tj) + a[j0 + 1, i0] * (1 - ti) * tj +
                a[j0 + 1, i0 + 1] * ti * tj)

    def lay(self, pl, top_abs, mask, cx, cy, psi):
        """Set a plate down: the cells under its footprint take its (absolute) top."""
        xs = self.x0 + (np.arange(self.nx) + 0.5) * TEXEL
        ys = self.y0 + (np.arange(self.ny) + 0.5) * TEXEL
        W, H = pl["size"]
        p = math.radians(psi)
        ox = cx + pl["at"][0] * math.cos(p) - pl["at"][1] * math.sin(p)
        oy = cy + pl["at"][0] * math.sin(p) + pl["at"][1] * math.cos(p)
        r = 0.5 * math.hypot(W, H) + TEXEL
        ii = np.nonzero((xs > ox - r) & (xs < ox + r))[0]
        jj = np.nonzero((ys > oy - r) & (ys < oy + r))[0]
        XW, YW = np.meshgrid(xs[ii], ys[jj])
        dx, dy = XW - ox, YW - oy
        u = dx * math.cos(p) + dy * math.sin(p)
        v = -dx * math.sin(p) + dy * math.cos(p)
        nv, nu = top_abs.shape
        fi = np.clip(((u + W / 2) / W * nu - 0.5).round().astype(int), 0, nu - 1)
        fj = np.clip(((H / 2 - v) / H * nv - 0.5).round().astype(int), 0, nv - 1)
        inside = (np.abs(u) <= W / 2) & (np.abs(v) <= H / 2) & mask[fj, fi]
        blk = self.top[np.ix_(jj, ii)]
        self.top[np.ix_(jj, ii)] = np.where(inside, np.maximum(blk, top_abs[fj, fi]), blk)

    def smoothed(self, sigma_m):
        from scipy.ndimage import gaussian_filter
        w = World.__new__(World)
        w.x0, w.y0, w.nx, w.ny = self.x0, self.y0, self.nx, self.ny
        w.top = gaussian_filter(self.top, sigma_m / TEXEL).astype(np.float32)
        return w


def plate_world(pl, cx, cy, psi, step=1):
    U, V = grid(pl)
    U, V = U[::step, ::step] + pl["at"][0], V[::step, ::step] + pl["at"][1]
    p = math.radians(psi)
    return cx + U * math.cos(p) - V * math.sin(p), cy + U * math.sin(p) + V * math.cos(p)


def base_z(world, plates, rel, cx, cy, psi, step=2):
    """The rigid sliding sheet's base: the highest point its underside meets (0 on bare oak)."""
    z = 0.0
    for pl in plates:
        top_rel, bot_rel, mask = rel[pl["name"]]
        X, Y = plate_world(pl, cx, cy, psi, step)
        under = world.sample(X, Y)
        m = mask[::step, ::step]
        z = max(z, float((under - bot_rel[::step, ::step])[m].max()))
    return z


DRAPE = 0.006                                # relief.DRAPE: paper bridges what lies beneath over about 6 mm


def lie_down(world, pl, rel, cx, cy, psi, z_rigid):
    """The resting lie: each point of a paper sheet on what is under it (the higher of that and its 6 mm smoothing:
    paper bridges small gaps and never sinks into what it lies on), its own relief on top; the Atlas boards rigid.
    Returns (bottom, top) absolute on the plate's texels, and the lie: bottom minus the rigid lie (the shape key)."""
    top_rel, bot_rel, mask = rel[pl["name"]]
    if pl["kind"] == "board":
        return z_rigid + bot_rel, z_rigid + top_rel, np.zeros_like(bot_rel)
    X, Y = plate_world(pl, cx, cy, psi)
    under = np.maximum(world.sample(X, Y), world.smoothed(pl.get("drape", DRAPE)).sample(X, Y))
    bottom = under + bot_rel
    return bottom, bottom + (top_rel - bot_rel), (bottom - (z_rigid + bot_rel)).astype(np.float32)


def edge_gaps(world, pl, rel, cx, cy, psi, bottom):
    """The air under a resting sheet along its outline (what its contact shadow is drawn from), in mm."""
    top_rel, bot_rel, mask = rel[pl["name"]]
    X, Y = plate_world(pl, cx, cy, psi)
    under = world.sample(X, Y)
    ring = mask.copy()
    ring[1:-1, 1:-1] = mask[1:-1, 1:-1] & ~(mask[:-2, 1:-1] & mask[2:, 1:-1] & mask[1:-1, :-2] & mask[1:-1, 2:])
    return ((bottom - under)[ring] * 1e3).astype(np.float32)


def _gap_stats(g):
    return {"median_mm": round(float(np.median(g)), 3), "p95_mm": round(float(np.percentile(g, 95)), 3),
            "max_mm": round(float(g.max()), 3)}


def _rows(s):
    rows = []
    for f in range(L.FRAMES):
        t = L.t_of(f)
        cx, cy = L.centre_at(s, t)
        rows.append({"f": f, "c": [round(cx, 6), round(cy, 6)], "psi": round(L.psi_at(s, t), 5),
                     "lift": round(L.lift_at(s, t), 6), "lie": round(L.lie_at(s, t), 6), "vis": L.visible_at(s, t),
                     "z": None})
    return rows


def _settle(world, plates, rel, s, rows, store, report, sid, lay=True):
    """Slide a sheet over the pile as it stands (rigid, every frame), then let it lie down at rest."""
    z_rest = base_z(world, plates, rel, *s["land_centre_m"], s["land_psi_deg"])
    for r in rows:
        moving = r["vis"] and L.t_of(r["f"]) < s["stop_s"]
        r["z"] = round(base_z(world, plates, rel, *r["c"], r["psi"]) if moving else z_rest, 6)
    gaps, lays = [], []
    for pl in plates:
        bottom, top, lie = lie_down(world, pl, rel, *s["land_centre_m"], s["land_psi_deg"], z_rest)
        store[f"{pl['name']}|lie"] = lie
        gaps.append(edge_gaps(world, pl, rel, *s["land_centre_m"], s["land_psi_deg"], bottom))
        lays.append((pl, top))
    if lay:
        for pl, top in lays:
            world.lay(pl, top, rel[pl["name"]][2], *s["land_centre_m"], s["land_psi_deg"])
    report["rest"][sid] = {"z_rigid_mm": round(z_rest * 1e3, 3), "pile_top_mm": round(float(world.top.max()) * 1e3, 3)}
    report["edge_gaps"][sid] = _gap_stats(np.concatenate(gaps))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rel, store = {}, {}
    for pl in PLATES:
        top, bot, mask = own_relief(pl)
        rel[pl["name"]] = (top, bot, mask)
        s = sheet_of(pl["sheet"])
        store[f"{pl['name']}|top"] = top
        store[f"{pl['name']}|bottom"] = bot
        store[f"{pl['name']}|mask"] = mask
        store[f"{pl['name']}|lift"] = lift_profile(pl, s)
        print(f"{pl['name']:28s} {top.shape} relief {bot.min() * 1e3:.2f}..{bot.max() * 1e3:.2f} mm, top max "
              f"{top.max() * 1e3:.2f} mm, mask {mask.mean():.3f}")
    world = World()
    poses, report = {}, {"solved": L.solved_table(), "rest": {}, "edge_gaps": {}}
    for s in L.SHEETS:
        rows = _rows(s)
        _settle(world, [p for p in PLATES if p["sheet"] == s["id"]], rel, s, rows, store, report, s["id"])
        poses[s["id"]] = rows
    for k, r in L.RECORDS.items():                  # one record per film, each onto the same pile
        sid = f"R {k}"
        rows = _rows(r)
        _settle(world, [p for p in PLATES if p["sheet"] == sid], rel, r, rows, store, report, sid, lay=False)
        poses[sid] = rows
    np.savez_compressed(OUT / "plates.npz", **store)
    report["frame_cover"] = {str(f): L.topmost_cover(f) for f in (22, 37, 237, 391, 529, 651, 751)}
    (OUT / "poses.json").write_text(json.dumps({"fps": "30000/1001", "pile_centre": list(L.P), "plates": [
        dict(p) | ({"uv": mount_uv(p)} if p["kind"] == "mount" else {}) for p in PLATES],
        "poses": poses}), encoding="utf-8")
    (OUT / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({"rest": report["rest"], "edge_gaps": report["edge_gaps"]}, indent=1))


if __name__ == "__main__":
    main()
